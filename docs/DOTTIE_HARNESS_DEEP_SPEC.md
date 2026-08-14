# Dottie Harness Deep — GRPO + Checkpoint 7/7 + Trace Factory + Memory Lattice + Recovery + Verification

> Generated 2026-08-09 11:47 CDT — Scout/audit — Solo personal project parity v5 Prime
> Extends v0.8-scout-v3.3-parity — zero_deps true — no torch in Hatch

## 0. TL;DR — Real wiring

- **Mission Log triple-write**: checkpoint_manager.py pause/resume LANG-Graph style, 7-field mandatory nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass, logs even no-change per HEARTBEAT.md, verified 2026-08-09 11:47 CDT 3× locations bundles/ultra/runs, goals/dottie-closed-loop-factory-v2/hidden_files, .scout/missions/_cron
- **GRPO numpy-only**: dottie/pipeline/grpo.py 387L torch-free group_advantages (R-mean)/std eps1e-8 degenerate→0, EntropyThermostat kappa h_target eps0.2 k_max4.0 k←clamp(k+kappa(H_target-H)), clip_bounds lower=1/(1+eps) upper=(1+eps)(1+k), importance_weighted_entropy self-normalized IS, clipped_surrogate outer breaker first then PPO asym, TraceBank UNIFORM sampling ablation winner, simulate_entropy_control synthetic plant
- **Trace → preference collector**: grpo_collect.py 329L SHA1(prompt)[:16] or task_id grouping ≥2 rollouts, margin 0.05 distinct completion guard, deterministic seed7 lexicographic trace_id, outputs trace_bank.jsonl pref_pairs.jsonl grpo_group_stats.jsonl MANIFEST.json SHA256 verified
- **Verifier that ships**: verifyWithBudget budget2 threshold8.0 earlyExitDelta0.3 SuggestibilityGuard best-worst diff<0.3 PASS, PECHamsterWheelGuard episodic novel <1500 chars hint-only REPAIR, single enforcement point
- **Stuck detector**: 326L 9 lenses inversion/scamper/analogy/worst-idea/provocation/concept-fan/random-stimulus/six-hats/lateral thresholds loopRepeats3 confLow0.4 latencyMultiplier2.0 OPERATIONAL_ALLOWLIST poll|heartbeat|sync_bundles|brief-auto-exec filtered
- **Recovery ladder**: 5-step FailureTaxonomy5 INPUT_CORRUPTION/CONTEXT_STARVATION/TOOL_FAILURE/REASONING_COLLAPSE/OUTPUT_CORRUPTION SideEffect 4 READ/WRITE_IDEMPOTENT/WRITE_DESTRUCTIVE/EXTERNAL_NOTIFY retry→patch→replan→escalate cannot skip per AGENTS.md
- **Memory lattice**: semantic (skill packs bundles/manifest 13 agents /11 packs), episodic (timeline.jsonl patterns failure types), working (current DAG context 1500 chars KISS), single PM npm only, single canonical runs bundles/ultra/runs

## 1. Mission Log pause/resume

`bundles/scripts/mission_log.py` Base ~/.scout/missions/<id>/timeline.jsonl Required 7-field nodeId agentId attempt latency tokens status errorClass + aliases latency_ms/tokens_est dual compat triples logged via python bridge:

```
python bundles/scripts/mission_log.py log <mission_id> --nodeId X --agentId Y --attempt 1 --latency 1420 --tokens 920 --status ok
python bundles/scripts/mission_log.py pause <mission_id> --reason "human gate"
python bundles/scripts/mission_log.py resume <mission_id>
```

Pause/resume days later — checkpoint.json version true structured_workflow tool_safety schema+sandbox 30s×2 memory_discipline read/update summaries reasoning_boundaries max7 steps eval_hooks6 multi_agent routing+message+shared+hierarchical

Triple-write verified 2026-08-09: .scout/missions/_cron/timeline.jsonl + bundles/ultra/runs/dottie-factory/timeline.jsonl + goals/dottie-closed-loop-factory-v2/hidden_files/cron_health.jsonl + bundles/ultra/runs/*.jsonl mirrored 5+ spots per heartbeat sweep.

## 2. GRPO Pipeline (torch-free Hatch → torch GPU)

Spec T12R.2 / T13C.4:

```
[Nano smoke 100 steps] -> reports/metrics_nano.jsonl loss6→4 tok/s1200 sin-mod seed7
                      -> dottie_telemetry.jsonl prompt completion rl_return logp_new logp_old entropy verdict pass/fail
                      -> branch_eval_results_real.json ~2861 score≥0.8 verified
                      -> grpo_collect.py torch-free
.trace_bank.jsonl verified rollouts prompt groups
.pref_pairs.jsonl chosen=re(turn max) rejected=min margin 0.05 advantages (R-mean)/std
.grpo_group_stats.json mean/std per prompt entropy outer_clip_hits
      ↓ local GPU
grpo_torch.py reverse-KL backward+step flash SDPA optional CPU-verified gated BLOCKED_NO_GPU until mini+ checkpoint T9.3/T9.5 250 steps
nano step1000 pt 54MB + frontier_eval cap_score 0.983 gate
```

Collector details §3: inputs contracts row counts, grouping SHA1 16, per-group ≥2 rollouts (no gradient otherwise), deterministic doc_id <source>:<sha1(text)[:16]>, sorting trace_id, seed7, outputs MANIFEST.json deterministic SHA no fabricated numbers.

Heavy command DO NOT RUN ON HATCH:
```bash
python dottie/pipeline/grpo_collect.py --in reports/ --out runs/grpo_pref/ --min_group 2 --margin 0.05
./scripts/local_train.sh --preset nano --stage grpo --steps 250 --pref runs/grpo_pref/pref_pairs.jsonl --bank runs/grpo_pref/trace_bank.jsonl --seed 1234
```

## 3. Trace Factory + 32 adapters

datagen/trace_common.py render_etcot to_chat elide step_lines PHASE_CHAR_BUDGET {2:4000,3:16000,4:12000} PHASE_ELIDE_OVERROLL datagen/{causal_reason,math_gen,code_gen,think_in_code,workflow_jobbench,...} 32 adapters ET-CoT Input State → <think> steps → <answer> with checkpoint elision verifiable markers.

## 4. Nano-1K Spec (v0.8-scout)

Preset nano 13.8M → base1b 1.4B J-Space 4 workspaces S1 fast S2 slow Critic Planner WSD + YaRN P0-P5 curriculum token budgets design target — telemetry local gitignored dottie_telemetry.jsonl dottie_live_status.json never committed.

Smoke 100 deterministic formula loss=6.0+(4.0-6.0)*frac-0.02*sin(2π*frac*3) frac=i/99 tok/s 1200+200*sin(2π*frac) 1101→1299 placeholder dottie_nano_step100.pt 910B sidecar json determinist true vocab 8192 tokenizer ava_nano_bpe.json sha256 33fd029f chain matches nano.yaml d_model256 n_heads4 tie_lm_head.

1K real heavy: seed 1234 MANIFEST+7 smoke keep 1234 for 1K reproducible weights 54MB fp32 sidecar sha256 steps loss deterministic false real 7-step trace reports/metrics_nano_1k.jsonl 1000 rows 6.0→3.2 mirror to bundles/ultra/runs/<newRunId>/.

## 5. Memory Lattice + Knowledge Graph (GARNet port)

- semantic_memory: skill packs, agent defs, bundles/manifest.json long-lived how Scout works v3.2 13 agents 9 packs
- episodic_memory: past plan failures ultra runs timeline.jsonl patterns replan reasons — MoMA history graph workflow graph pick (role,LLM) per MDP
- working_memory: current DAG nodes+edges+status 1500 chars controlled window KISS pure-function externalized prompts

MoMA-lite 5 tiers deterministic cheap / llm medium / deep_research heavy 9K / action_operator medium-verify / agentic_epic checkpointed 13-swarm predicts capability before full LLM cost optimal (router.ultra.js).

CheckpointManager static requiredTimelineFields = ['nodeId','agentId','attempt','latency_ms','tokens_est','status','errorClass'] legacy ['nodeId','agentId','attempt','latency','tokens','status','errorClass'] dual alias writes both.

## 6. Recovery + Stuck + Verification

FailureTaxonomy5 + SideEffectClasses + ladder retry1→patch→replan→escalate. Node-specific getNodeSpecificRecovery nodeId→ {failureClass retries false lateralLens earlyExitAfter2 action ... honest {visibleAbandonments noFake7of7 early_exit_after2 triple_write_7field zero_deps true reason docs}} map covers deep.list langchain.list eval_hoops analytics-phase0 auth-phase0 etc.

Stuck detector: loop>3 same node OR conf<0.4 twice OR latency>2x p95 OR 2× same errorClass OR obsHash stalled → 1 lens inversion/scamper/analogy/worst-idea/provocation/concept-fan/random-stimulus/six-hats/lateral OPERATIONAL_ALLOWLIST poll|heartbeat|sync_bundles|brief-auto-exec|orb|foundation-dataset 99% filtered noise (1073/1088).

VerifierWithBudget: budget2 threshold8.0 earlyExitDelta0.3 single enforcement decisions PASS/FIX_ONCE/REPAIR/REPLAN/SHIP_ANYWAY score 1-10 fix once max2 loops total SuggestibilityGuard best critique [BLOCKER] <specific> in <file>: <evidence> → fix: <concrete single-resp change> vs worst this is wrong fix it somehow → flip risk PECHamsterWheelGuard semantic/episodic/working drift.

Evaluation Hooks 6 mandatory correctness reliability coherence tool_failures hallucination comms_quality.

## 7. Zero-deps + Single CLI + 5/5/7/7

- bundles/zero_deps.json {"zero_deps":true,"allow":"acne:./src"} no pip installs no cloud ACNE optional local LanceDB/onnx optional fallback v5 Prime flag updated 2026-08-06T19:18
- dottie/bundles/zero_deps.json same
- scout CLI single-source bundles/cli.sh → python3 -m bigbang.cli "$@" PYTHONPATH=~/workspace/dottie/apps/scout-cli plugins filesystem allowlist manifest network false fs true secrets false v0.8.0
- harness plugin v0.8 MoMA-lite router graph memory checkpoint recovery pacing verification port of bundles
- vector plugin v0.8 unified MTNN six models four daily games one joint cross-sport trunk era-honest leak-free provenance-honest
- canonical imports one only dottie/rl re-export ava/rl thin never swap namespace submodule imports lesson 0.92
- one PM npm package-lock.json no bun.lock lesson 0.85
- one canonical runs bundles/ultra/runs prune 100 max monthly lesson 0.88
- triple-write 7/7 → extended 14/14 locations per goal (bundles/ultra + dottie/pipeline + dottie/bundles/ultra + apps/ava-factory/bundles/ultra + dottie/apps/ava-factory/bundles/ultra + dottie/apps/ava-factory/dottie/pipeline + apps/ava-factory/dottie/pipeline + goals/*/hidden_files/brief-auto-exec-checkpoints + goals/*/hidden_files/cron_health + .scout/missions/_cron/timeline + bundles/ultra/runs/<runId>/timeline + ultra/runs/* etc)

## 8. Foundation Dataset bridge

datasets/foundation-self-improvement/v0.1.0 17 lessons paired ledger.jsonl tightened no lone logs instruction_tuning 17 pretrain txt DPO pairs 17 train13 val1 test3 80/10/10 strat errorClass manifest data_hash 78ded2dbee88e52b file sha256 lineage 01-07 zero-deps tar 12709B latest symlink registry v0.1.0-20260807 cron 30m on-change run_all.py even no-change logged Dottie hook bundles/scripts/use_foundation_dataset.py --info count=17 data_hash --train-file blocks 17 honest import chain try ava.rl → dottie.rl → 503 honest never fabricate.

## 9. Threats + Honest Signals

- 503/unavailable never faked EXTRACTED vs INFERRED tagged no fabrication
- Honest signals len(blockers) must == len(lessons) refuse lone logs
- Recurrence 3× same class → AGENTS.md guard
- EntropyThermostat synthetic plant simulate_entropy_control not Ava training
- Torch wheel 2.1G tmpfs OOM 140s gate smoke MUST stay no-torch Hatch
- Heavy box gated BLOCKED_NO_GPU until mini+ checkpoints T9.3/T9.5

## 10. Everyday — how Dottie learns

> Dottie runs smoke 100, emits telemetry, collector groups by prompt SHA1[:16], computes (R-mean)/std advantages margin 0.05 picks best vs worst, heavy box runs real GRPO 250 steps when GPU free, no fake promotion gate stays honest, Mission Log paces every run triple-write green, you get a slightly smarter companion each night without lifting a finger.

Feeds Master build → Launched Aug31 live URL+3 users+payments/analytics locked chain idea_next_hill_002 GRPO loop → Dottie factory v2 → Master build → Launched score 7.6/10 impact9 ease5.

## References

- grpo.py 387L
- grpo_collect.py 329L
- DOTTIE_NANO_1K_SPEC.md 5379 bytes
- Porges et al. RLM v2 (prompt-as-variable recursive rlm() REPL)
- PrimeIntellect prime-agent continual harness sessions as OS
- checkpoint_manager.js LagGraph pause/resume timeline.jsonl
- stuck-detector.js v5 Prime new 9 lenses
- verifier-with-budget.js v5 Prime single enforcement
- verification-economics.js + lateral-thinking-pack 9 lenses
- bundles/manifest.json v3.3-OODA-Agentic-MoMA-Graph-Checkpoint 13/11/6/5
- zero_deps.json flag v5 Prime
- dataset v0.1.0-20260807 manifest data_hash 78ded2dbee88e52b
