# CodeAct / LLM-VM plan — code as the model's action substrate (spec 13)

Date: 2026-07-17
Source: MAI-Thinking-1 agentic SWE + tool-use findings → `docs/RL_INTEGRATION.md`
Contract: `specs/13_codeact.md` (T13C.1–T13C.6)
Builds on: `specs/12_rl_training.md` (CodeAct is an agentic mode of the GRPO loop, not a parallel system)
Status: **ALL code halves landed 2026-07-17 — including the torch halves.** The nano CPU pilot ran
the real chain end-to-end (`scripts/cpu_pilot_e2e.py`: corpus → tokenizer → pack → 90-step pretrain
→ real agentic branch fork) and `scripts/rl_smoke_update.py` executed a real GRPO update on the real
branch checkpoint via the real decode policy (`ava/rl/codeact_policy.py`) + real torch step
(`ava/rl/grpo_torch.py`) + real sandbox rollouts. Evidence: `runs/cpu_pilot/MANIFEST.json`
(scale=smoke_cpu_pilot, capability_claim=none). **Remaining gates are resources, not code:**
capability-scale climbs (mini+ checkpoints, GPU wall-clock), the MOPD merge, the EG verdict.

## Objective

Make Ava *think in code*: the model's actions are executable Python run in a persistent, sandboxed
LLM-VM with tools bound as callables; observations are real stdout/return values. Turn "leverage
tools to execute workflows we care about" into a trainable, verifiable objective instead of narrated
ReAct text that never runs.

## Phase order (do not skip)

1. **Sandbox (T13C.1) — ✅ DONE (2026-07-17)** — `ava/rl/codeact_sandbox.py`, multi-turn persistent
   namespace via a long-lived worker subprocess, per-step wall cap (setsid+killpg), POSIX resource
   caps, guarded open/blocked socket+fork, importable-or-source tools with call accounting,
   deterministic replay. `tests/test_codeact_sandbox.py` 14/14. Extends `code_gen.run_sandboxed`.
2. **Datagen (T13C.2) — ✅ DONE (2026-07-17)** — `ava/datagen/codeact.py`, 4 executable families,
   grounding-share floor, answers computed by running code; every trajectory re-executes through the
   T13C.1 Sandbox to the labeled answer. `tests/test_codeact_datagen.py` 10/10.
3. **Eval (T13C.3) — ✅ scoring engine DONE** — `evals/codeact_eval.py`: real sandbox `score_emission`
   + seed-sensitive `simulate_policy_eval` + `run_codeact_eval` now **wired to the T13C.5 decode
   loop** (fails at the honest ModelPolicy gate, not a stub).
4. **RL terms + discipline (T13C.4) — ✅ GPU-free DONE** — `ava/rl/codeact_rewards.py`
   (`r_exec`/`r_codeuse`/`r_len`/`codeact_return`) + `ava/rl/grpo.py` (group advantages, entropy
   thermostat, outer ratio clip, trace bank + uniform recovery; synthetic servo demo of the
   thermostat). The **torch optimizer step** (`GRPOOptimizerStep.step`) refuses without a checkpoint
   + GPU.
5. **Consolidate + serve (T13C.5) — ✅ GPU-free DONE** — `ava/rl/codeact_loop.py` (pluggable-Policy
   emit→sandbox→observe→FINAL, sanitized user output + captured trace, model-free replay harness) +
   `ava/rl/codeact_consolidation.py` (verified-only, stratified MOPD trace-pool prep). The **real
   model policy** and the **MOPD distillation run** refuse (gated).
6. **EG gate (T13C.6) — ✅ adapter DONE** — `ava/rl/codeact_eg_gate.py`: success→error transform +
   `eg_trend` verdict, tested on synthetic ladders. `codeact_eg_gate_from_eval` **refuses** the
   honest-fail eval records; the real verdict waits on the climb.

## Gates

| Gate | Math | Target |
|------|------|--------|
| G1 isolation | fork bomb / socket open / out-of-scratch write | killed/blocked + reported, host unharmed |
| G2 determinism | replay (seed, tools, program) | byte-identical Observations |
| G3 datagen honesty | re-exec emitted trajectories | 100% reach labeled answer; no answer leakage |
| G4 eval sensitivity | break a tool binding | success rate drops measurably |
| G5 no narrated-code hack | non-executing code vs running code | penalized; `R_exec` secondary to `R_task` |
| G6 promotion | `eg_trend(nano, mini)` vs non-CodeAct agentic baseline | `promote` |

## Open questions (log answers here)

- Tool-binding surface: start with `react_tools` tools (calculator, get_clock, read/cite) — which
  subset is dense enough to train on without becoming a memorized API?
- Step cap vs task difficulty: a fixed cap penalizes hard multi-step tasks; scale the cap with the
  same historical pass-rate difficulty signal as the length penalty?
- Redundant-call detection: reuse scout-cli RFT `reward_components.redundant_steps` semantics over
  sandbox tool-call logs, or define fresh? Keep the definition versioned (spec 12 naming guard).
- Safety set for the interpreter: which "refuse to run this" cases belong in the Critic-scoped
  set before CodeAct serving is exposed?
