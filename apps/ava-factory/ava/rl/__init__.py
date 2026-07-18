# Solo personal project, no connection to employer, built with public/free-tier only
"""ava.rl — reinforcement-learning + agentic-execution substrate (specs 12 & 13).

GPU-free, tested building blocks landed:
  * `codeact_sandbox`       — the LLM-VM (T13C.1): subprocess-isolated persistent-namespace interpreter.
  * `codeact_rewards`       — R_exec / R_codeuse / R_len / codeact_return (T13C.4 reward terms).
  * `grpo`                  — GRPO-lite discipline mechanics (T12R.2 / T13C.4): group advantages,
                              entropy-thermostat controller, outer ratio clip, trace-bank recovery.
  * `grpo_torch`            — the REAL torch GRPO optimizer step (T12R.2 torch half): exact-parity
                              clipped surrogate, thermostat/outer-clip wiring, backward + step.
                              CPU-verified: learning demo + spike/overflow NaN-survival tests.
  * `codeact_loop`          — pluggable-policy decode/serving loop (T13C.5): emit→sandbox→observe→FINAL.
  * `codeact_policy`        — the REAL autoregressive decode policy (T13C.5): TorchModelPolicy over
                              any torch LM + duck-typed tokenizer; greedy/sampling, seeded, stop-cut.
  * `codeact_consolidation` — MOPD trace-pool prep (T13C.5): verified-only, stratified.
  * `codeact_eg_gate`       — EG-gated rollout (T13C.6): success→error transform + eg_trend verdict.

The whole mechanical chain (decode → sandbox → rewards → advantages → torch update) has been
executed END-TO-END on a REAL smoke-scale checkpoint: `scripts/cpu_pilot_e2e.py` runs the real
nano CPU-pilot pipeline (datagen → tokenizer → pack → pretrain → agentic branch fork) and
`scripts/rl_smoke_update.py` performs a real GRPO update on the resulting branch checkpoint
(evidence: `runs/cpu_pilot/MANIFEST.json`, scale=smoke_cpu_pilot, capability_claim=none).

Still gated — now on CAPABILITY-scale resources only, not missing code: capability-level branch
checkpoints (T9.3/T9.5 at mini+; GPU wall-clock), the MOPD distillation run
(`codeact_consolidation.mopd_consolidation_run`), and the EG verdict (needs real 2-rung capability
curves). The legacy refusal stubs (`grpo.GRPOOptimizerStep`, `codeact_loop.ModelPolicy`) now point
to their real implementations and continue to refuse fabricated use.
"""
