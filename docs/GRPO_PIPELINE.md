# GRPO Pipeline — Nano Reasoning Distillation

> Solo personal project, no connection to employer, built with public/free-tier only
> Dottie / Ava v6.4 — optimizer traces → nano GRPO prep
> Branch: scout/dottie-traces-grpo | Status: scaffold / numpy-only in Hatch

## 0. TL;DR

We have real GRPO mechanics (spec 12 T12R.2 / spec 13 T13C.4) already landed:
- `dottie/rl/grpo.py` — 387 lines, torch-free: `group_advantages`, `EntropyThermostat`, `clipped_surrogate`, `TraceBank`, `importance_weighted_entropy`, `simulate_entropy_control`
- `dottie/rl/grpo_torch.py` — real torch optimizer step, CPU-verified, gated `BLOCKED_NO_GPU` until mini+ checkpoints (T9.3/T9.5)
- `tests/test_grpo.py` + `test_grpo_torch.py` — 24+ cases, thermostat/clip/bank behavior
- `datagen/trace_common.py` + `compress_trace.py` + `db_trace.py` — ET-CoT execution traces (Input State → <think> steps → <answer>), with checkpoint elision

Missing until this lane: a bridge that reads nano eval / agentic traces emitted on Hatch (numpy/jsonl) and turns them into GRPO-ready preference pairs, so local GPU can run the real GRPO update without re-running eval.

This doc is the contract. `dottie/pipeline/grpo_collect.py` is the numpy-only implementation.

## 1. What Exists Today — Audit 23:01 CDT

### 1.1 Pipeline skeleton (ava/pipeline → dottie/pipeline)
```
collector.py  → curator.py → pack.py → split.py → trainer
            ↘ demand.py / flow.py / manifest.py (SQLite, RAW→CLAIMED_CURATE→PACKED→CLAIMED_TRAIN→CONSUMED)
```
- `collector.py` — RAW shard production, cursor-based resumability, .tmp→atomic replace, doc_id SHA1 dedup
- `curator.py` — decontam / dedup / quality_taxonomy filtering
- `pipeline/runs/dottie-*/` — 5 runs currently (030140Z, 031150Z, 031319Z, 034534Z-lane2-polish, 035956Z), each with 7-field checkpoint.json
- `pipeline_status.py` — fallback chain: `AVA_REPORTS_DIR → DOTTIE_TELEMETRY_DIR → repo reports → /reports` verified fixed 03:45 CT

### 1.2 RL substrate (dottie/rl)
- `grpo.py` — math only, no torch import
  - `group_advantages(returns: Sequence[float]) → List[float]`  : (R-mean)/std
  - `EntropyThermostat(kappa, h_target, eps=0.2, k_max=4.0, k)` : k ← clamp(k + κ·(H_target-H),0,k_max), clip_bounds lower=1/(1+ε) upper=(1+ε)(1+k)
  - `importance_weighted_entropy(logp_new, logp_old) → float` : self-normalized IS H≈Σw·(-logp_new)/Σw
  - `clipped_surrogate(ratio, adv, lower, upper, r_outer) → SurrogateResult` : outer breaker first, then PPO asymmetric unclipped zones
  - `TraceBank` : append verified rollouts, per-prompt-capped, prompt-deduped, UNIFORM recovery sampling (ablation winner)
  - `simulate_entropy_control` : synthetic plant proving thermostat drives H→H_target, NOT Ava training
- `grpo_torch.py` — reverse-KL, backward+step, flash SDPA optional
- `codeact_*` — T13C agentic loop: `codeact_sandbox` subprocess LLM-VM, `codeact_policy` TorchModelPolicy, `codeact_loop` emit→sandbox→observe→FINAL, `codeact_rewards` R_exec/R_codeuse/R_len, `codeact_eg_gate` success→error EG

### 1.3 Traces + evals
- `datagen/trace_common.py` — `render_etcot`, `to_chat`, `elide`, `step_lines`, PHASE_CHAR_BUDGET {2:4000,3:16000,4:12000}, PHase_ELIDE_OVER
- `datagen/{causal_reason,math_gen,code_gen,think_in_code,workflow_jobbench,...}` — 32 adapters
- `reports/` — branch_eval_results_*.json, frontier_eval_results.json, eval_{preset}_base.json, self_distill_checkpoint.json, ava_telemetry.jsonl, dottie_telemetry.jsonl, metrics_nano.jsonl (100 rows loss 6→4 tok/s 1200)
- Gap: no `dottie/pipeline/grpo_collect.py` to turn those jsonls into `pref_pairs.jsonl` for GRPO

## 2. Desired Flow — Nano 100 → Nano GRPO

```
[ Nano smoke 100 steps ]
       ↓ eval / telemetry
reports/metrics_nano.jsonl
dottie_telemetry.jsonl
branch_eval_results_real.json
eval_artifacts.py resolved jsons
       ↓ (this lane) grpo_collect.py — torch-free
.trace_bank.jsonl  (verified rollouts, prompt groups)
.pref_pairs.jsonl  (chosen vs rejected, with A_i)
.grpo_group_stats.json  (mean/std per prompt, entropy, outer_clip_hits)
       ↓ (local GPU) grpo_torch.py / on_policy_distill.py
nano step1000 pt + frontier_eval cap_score 0.983 gate
```

## 3. Collector — Design (no torch in Hatch)

### 3.1 Input contracts
| File | Rows | Key fields | Filter |
|------|------|------------|--------|
| `reports/metrics_nano.jsonl` | 100 | `step`, `loss`, `tok/s`, `lr` | loss↓ 6→4 verification |
| `reports/dottie_telemetry.jsonl` | N | `prompt`, `completion`, `rl_return`, `logp_new`, `logp_old`, `entropy`, `verdict` | verdict∈{pass,fail} |
| `reports/branch_eval_results_real.json` | ~2861 | `task_id`, `trace`, `answer`, `score` | score≥0.8 → verified |
| `apps/ava-factory/dottie/datagen/trace_common` rendered docs | any | `task`, `think_lines`, `answer_lines` | via `render_etcot` |

If missing, collector emits empty bank + warning — never crashes.

### 3.2 Group formation
- Group key = `prompt_hash = SHA1(prompt)[:16]` or `task_id` when prompt absent
- Per group: gather ≥2 rollouts required for GRPO variance; singletons dropped (correct: no gradient signal)
- Rollout fields preserved: `prompt`, `completion`, `rl_return` (aka R), `logp_new`, `logp_old`, `trace_id`, `model_ckpt`, `entropy`, `verdict`

### 3.3 Advantage + preference pair emission
- `advantages = group_advantages(returns)` from `dottie.rl.grpo` logic (mean-centered, population std, eps 1e-8 degenerate→0 advantage)
- Chosen = max(returns) rollout, Rejected = min(returns) — only when max>min + margin 0.05 (filters noisy ties)
- Preference pair schema:
```json
{
  "prompt_id": "sha1:16",
  "prompt": "<|user|> ...",
  "chosen": {"completion": "...", "trace_id": "...", "return": 0.94, "adv": 1.12, "entropy": 0.28},
  "rejected": {"completion": "...", "trace_id": "...", "return": 0.12, "adv": -1.08, "entropy": 0.42},
  "group_size": 4,
  "group_mean": 0.51,
  "group_std": 0.33,
  "delta_return": 0.82
}
```
- `trace_bank` entry keeps full group for entropy thermostat & recovery sampling

### 3.4 Entropy & outer clip stats
- Collector re-computes `clipped_surrogate` for stats only (no backprop): ratio = exp(logp_new-logp_old) mean, or 1.0 when logps missing
- `importance_weighted_entropy` called torch-free (math.exp math only)
- Emits `group_stats.jsonl`: per group `h_policy`, `k`, `clip_bounds`, `outer_clip_hits`

### 3.5 Determinism
- Fixed seed = 7 (matches nano smoke), sorting lexicographic on trace_id
- doc_id = `<source>:<sha1(text)[:16]>` matches collector.py
- Output idempotent: same input → same sha1’d pairs

## 4. Local GPU Handoff — What Heavy Box Does With This

1. `python dottie/pipeline/grpo_collect.py --in reports/ --out runs/grpo_pref/ --min_group 2 --margin 0.05`
2. Verify `pref_pairs.jsonl` >0 groups, then:
   ```
   ./scripts/local_train.sh --preset nano --stage grpo --steps 250 \
     --pref runs/grpo_pref/pref_pairs.jsonl \
     --bank runs/grpo_pref/trace_bank.jsonl \
     --seed 1234
   ```
   Real update uses `grpo_torch.py`: thermostat κ=0.5 h_target=0.3 eps=0.2 k_max=4.0, outer r_outer=1.0, inner lower/upper from thermostat, Adv from group_advantages, loss = -mean(clipped_surrogate.objective), backward + AdamW8bit.

3. Gate: `frontier_eval cap_score 0.983 && tokens_total==2048000 && vocab_sha==33fd029f...` → emit `dottie_nano_step1000.pt` ~54MB fp32 14M params

## 5. Risks / Anti-patterns

- No torch pip in Hatch — OOM 2.1G tmpfs; keep to numpy/stdlib/json
- No fabricated numbers: advantages are computed, not assumed; degenerate groups → ~0 advantage → no gradient (correct)
- Recovery sampling must be uniform per ablation; never bias toward high-return (distorts thermostat)
- Elision markers `[.. K steps elided ..]` must carry state checkpoint so tail remains verifiable

## 6. This Lane’s Deliverables

- [x] Audit existing trace/GRPO presence (this doc §1)
- [ ] `docs/GRPO_PIPELINE.md` (this file) — spec + audit
- [ ] `dottie/pipeline/grpo_collect.py` — numpy-only, reads jsonl, emits pref pairs + trace bank + group stats
- [ ] Copy spec+collector to `apps/ava-factory/docs/GRPO_PIPELINE.md` compat & verify `pytest tests/test_grpo.py -q` passes (8 core tests)
- [ ] Branch `scout/dottie-traces-grpo` pushed, claim board row DONE

## 7. References

- `on_policy_distill.py` — MOPD multi-teacher + privileged + earlier teacher patterns, YaRN 10k→1M, 4 workspaces, WSD warmup 2000 stable 736k
- `pipeline/collector.py` — RAW shard cursor/dedup, .tmp atomic replace
- `jlosses.py` / `llmvm` / `eval_harness.py` — eval → telemetry → reward shaping
- `config.py` / `hub_manifest.json` — preset rung ordering nano→mini
